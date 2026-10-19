type DataRecord = Record<string, unknown>;

export type USPeerDirection = "positive" | "negative" | "flat" | "unknown";
export type USPeerListName = "positive" | "negative" | "flat" | "unknown";

export interface USMappingPeerObservation {
  id: string;
  hkSymbol: string;
  hkName: string;
  usSymbol: string;
  sourceSession: string;
  returnPct: number | null;
  returnLabel: string;
  direction: USPeerDirection;
  stockDirectionLabel: string;
  hasMixedStockDirection: boolean;
  peerBucket: string;
  catalogSegment: string;
  relationId: string;
  relationType: string;
  catalogFact: string;
  catalogMechanism: string;
  catalogFailure: string;
  catalogCondition: string;
  quoteStatus: string;
  statusDetail: string;
  consumerRetail: boolean;
}

export interface USMappingPeerLists {
  sourceSession: string;
  targetDate: string;
  formalTargetEligibility: string;
  acceptedRelationCount: number;
  mixedStockCount: number;
  observations: USMappingPeerObservation[];
  positive: USMappingPeerObservation[];
  negative: USMappingPeerObservation[];
  flat: USMappingPeerObservation[];
  unknown: USMappingPeerObservation[];
}

const ACCEPTED_DISPOSITION = "ADOPTED_BUSINESS_PEER";
const BUSINESS_PEER_ROUTE = "SUBINDUSTRY_BUSINESS_PEER";
const CONSUMER_RETAIL_LABEL = /(消费|零售|餐饮|食品|饮品|饮料|调味|包袋|箱包|户外|旅行用品|纸品|卫生用品|日化|美妆|服饰|运动|家居|家电|乳品|添加剂|洗护|个人护理)/i;

function asRecord(value: unknown): DataRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as DataRecord
    : null;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return "";
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    const result = text(value);
    if (result) return result;
  }
  return "";
}

function numericReturn(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function returnLabel(rawValue: unknown, parsed: number | null): string {
  if (parsed === null) return "涨跌未知";
  const value = text(rawValue) || String(parsed);
  return `${parsed > 0 && !value.startsWith("+") ? "+" : ""}${value}%`;
}

function relationField(relation: DataRecord, field: string): string {
  const source = asRecord(relation.catalog_source_record);
  const rawSource = asRecord(relation.source_record);
  const nestedRelation = asRecord(relation.catalog_relation);
  return firstText(
    relation[`catalog_${field}`],
    source?.[field],
    rawSource?.[field],
    nestedRelation?.[field]
  );
}

function normalizedDirection(value: number | null): USPeerDirection {
  if (value === null) return "unknown";
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return "flat";
}

function validSessionDate(value: string): boolean {
  if (!/^\d{8}$/.test(value)) return false;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year
    && date.getUTCMonth() === month - 1
    && date.getUTCDate() === day;
}

function statusDetail(input: {
  quoteStatus: string;
  hasReturn: boolean;
  coverageState: string;
  sourceDateMismatch: boolean;
  sessionEvidenceMissing: boolean;
  sessionEvidenceInvalid: boolean;
  returnMismatch: boolean;
}): string {
  const details: string[] = [];
  if (input.quoteStatus !== "VERIFIED") {
    details.push(input.quoteStatus ? `报价状态 ${input.quoteStatus}` : "报价状态未知");
  }
  if (!input.hasReturn) details.push("来源涨跌缺失或格式无效");
  if (input.coverageState !== "READY") {
    details.push(input.coverageState ? `同行组状态 ${input.coverageState}` : "同行组状态缺失");
  }
  if (input.sessionEvidenceMissing) details.push("美股来源会话日期证据缺失");
  if (input.sessionEvidenceInvalid) details.push("美股来源会话日期格式无效");
  if (input.sourceDateMismatch) details.push("报价会话与保存版本来源会话不一致");
  if (input.returnMismatch) details.push("同行组成员收益与关系报价不一致");
  return details.join("；") || "来源报价已核验";
}

function stockDirectionLabel(directions: Set<USPeerDirection>): string {
  const hasPositive = directions.has("positive");
  const hasNegative = directions.has("negative");
  const hasFlat = directions.has("flat");
  const hasUnknown = directions.has("unknown");
  if (hasPositive && hasNegative) return "同一港股正负同行观察并存";
  if (hasPositive && hasUnknown) return "有正向观察，另有待核关系";
  if (hasNegative && hasUnknown) return "有负向观察，另有待核关系";
  if (hasPositive) return "仅见正向同行来源观察";
  if (hasNegative) return "仅见负向同行来源观察";
  if (hasFlat && hasUnknown) return "零变动观察及待核关系";
  if (hasFlat) return "零变动来源观察";
  return "来源方向待核";
}

function consumerRetailLabel(basket: DataRecord, relation: DataRecord): boolean {
  const sourceRecord = asRecord(relation.catalog_source_record);
  const values = [
    basket.peer_bucket,
    relation.catalog_segment,
    relation.catalog_research_industry,
    relation.catalog_research_segment,
    sourceRecord?.segment,
    sourceRecord?.["研究行业"],
    sourceRecord?.["商品类型"]
  ];
  return values.some(value => CONSUMER_RETAIL_LABEL.test(text(value)));
}

function createObservation(
  input: unknown,
  memberValue: unknown,
  basket: DataRecord,
  relation: DataRecord,
  stockNames: Map<string, string>,
  sourceSession: string
): USMappingPeerObservation {
  const hkSymbol = firstText(input);
  const member = asRecord(memberValue) || {};
  const quote = asRecord(relation.quote) || {};
  const nestedRelation = asRecord(relation.catalog_relation) || {};
  const relationId = firstText(relation.catalog_relation_id);
  const usSymbol = firstText(member.symbol, relation.us_symbol, quote.symbol) || "美股代码未知";
  const memberReturnRaw = member.return_pct;
  const quoteReturnRaw = relation.us_source_return_pct;
  const returnRaw = memberReturnRaw === null || memberReturnRaw === undefined || memberReturnRaw === ""
    ? quoteReturnRaw
    : memberReturnRaw;
  const memberReturn = numericReturn(memberReturnRaw);
  const quoteReturn = numericReturn(quoteReturnRaw);
  const parsedReturn = numericReturn(returnRaw);
  const returnMismatch = memberReturn !== null && quoteReturn !== null
    && Math.abs(memberReturn - quoteReturn) > 1e-8;
  const quoteStatus = firstText(relation.quote_status, quote.status) || "UNKNOWN";
  const relationSession = firstText(relation.source_session);
  const quoteSession = firstText(quote.session_date);
  const actualSession = quoteSession || relationSession || sourceSession;
  const sourceSessionReferences = [sourceSession, relationSession].filter(Boolean);
  const observedSessions = [sourceSession, relationSession, quoteSession].filter(Boolean);
  const sessionEvidenceMissing = !quoteSession || sourceSessionReferences.length === 0;
  const sessionEvidenceInvalid = observedSessions.some(session => !validSessionDate(session));
  const sourceDateMismatch = new Set(observedSessions).size > 1;
  const coverageState = firstText(basket.coverage_state);
  const hasReturn = parsedReturn !== null;
  const verified = quoteStatus === "VERIFIED" && hasReturn && !returnMismatch
    && !sourceDateMismatch && !sessionEvidenceMissing && !sessionEvidenceInvalid
    && coverageState === "READY";
  const direction = verified ? normalizedDirection(parsedReturn) : "unknown";
  const fact = relationField(relation, "fact") || "目录未提供可展示的关系事实，需补证。";
  const mechanism = relationField(relation, "mechanism") || "目录未提供明确传导机制；不据此推断港股方向。";
  const failure = relationField(relation, "failure") || "目录未提供关系风险说明，保持待核。";
  const condition = relationField(relation, "condition") || "目录未提供复核条件，需补证。";
  const catalogRelationName = firstText(nestedRelation.hk_name);
  const stockName = stockNames.get(hkSymbol) || firstText(relation.name, catalogRelationName);
  const sourceRecord = asRecord(relation.catalog_source_record);
  const consumerRetail = consumerRetailLabel(basket, relation);
  const detail = verified ? "来源报价已核验" : statusDetail({
    quoteStatus,
    hasReturn,
    coverageState,
    sourceDateMismatch: Boolean(sourceDateMismatch),
    sessionEvidenceMissing,
    sessionEvidenceInvalid,
    returnMismatch
  });
  const groupName = firstText(basket.peer_bucket) || "同行组未知";
  return {
    id: `${hkSymbol}:${groupName}:${relationId}:${usSymbol}`,
    hkSymbol,
    hkName: stockName || "名称未知",
    usSymbol,
    sourceSession: actualSession || "日期未知",
    returnPct: verified ? parsedReturn : null,
    returnLabel: verified ? returnLabel(returnRaw, parsedReturn) : (hasReturn ? `${returnLabel(returnRaw, parsedReturn)} · 待核` : "涨跌未知"),
    direction,
    stockDirectionLabel: "来源方向待核",
    hasMixedStockDirection: false,
    peerBucket: groupName,
    catalogSegment: firstText(relation.catalog_segment, relation.catalog_research_industry,
      sourceRecord?.segment, sourceRecord?.["研究行业"]),
    relationId: relationId || "关系编号未知",
    relationType: firstText(relation.relation_type, relation.route) || "关系类型未知",
    catalogFact: fact,
    catalogMechanism: mechanism,
    catalogFailure: failure,
    catalogCondition: condition,
    quoteStatus: verified ? "报价已核验" : `来源待核 · ${detail}`,
    statusDetail: detail,
    consumerRetail
  };
}

/**
 * Project the saved catalog's accepted business-peer baskets into visible source-market lists.
 * Direction is classified from verified US peer quotes only; HK eligibility and PIT remain separate.
 */
export function projectUSMappingPeerLists(value: unknown): USMappingPeerLists {
  const summary = asRecord(value) || {};
  const sourceSession = firstText(summary.source_session);
  const targetDate = firstText(summary.target_date);
  const formalTargetEligibility = firstText(summary.formal_target_eligibility) || "CANNOT_CONFIRM";
  const relationRows = asArray(summary.catalog_relation_dispositions)
    .map(asRecord)
    .filter((row): row is DataRecord => row !== null);
  const relations = new Map<string, DataRecord>();
  for (const row of relationRows) {
    const id = firstText(row.catalog_relation_id);
    if (id) relations.set(id, row);
  }
  const stockNames = new Map<string, string>();
  for (const rawRow of asArray(summary.rows)) {
    const row = asRecord(rawRow);
    if (!row) continue;
    const symbol = firstText(row.symbol);
    const name = firstText(row.name);
    if (symbol && name) stockNames.set(symbol, name);
  }

  const observations: USMappingPeerObservation[] = [];
  const basketsByStock = asRecord(summary.catalog_peer_baskets) || {};
  const seenRelations = new Set<string>();
  let acceptedRelationCount = 0;

  for (const [hkSymbol, rawBaskets] of Object.entries(basketsByStock)) {
    for (const rawBasket of asArray(rawBaskets)) {
      const basket = asRecord(rawBasket);
      if (!basket || firstText(basket.route) !== BUSINESS_PEER_ROUTE) continue;
      const members = asArray(basket.members).map(asRecord)
        .filter((member): member is DataRecord => member !== null);
      const relationIds = new Set<string>();
      for (const relationId of asArray(basket.relation_ids)) {
        const id = text(relationId);
        if (id) relationIds.add(id);
      }
      for (const member of members) {
        for (const relationId of asArray(member.relation_ids)) {
          const id = text(relationId);
          if (id) relationIds.add(id);
        }
      }

      for (const relationId of relationIds) {
        const relation = relations.get(relationId);
        if (!relation || firstText(relation.catalog_disposition) !== ACCEPTED_DISPOSITION) continue;
        const identity = `${hkSymbol}:${firstText(basket.peer_bucket)}:${relationId}`;
        if (seenRelations.has(identity)) continue;
        seenRelations.add(identity);
        acceptedRelationCount += 1;
        const matchingMembers = members.filter(member => asArray(member.relation_ids)
          .some(id => text(id) === relationId));
        const selectedMembers: unknown[] = matchingMembers.length ? matchingMembers : [null];
        for (const member of selectedMembers) {
          observations.push(createObservation(hkSymbol, member, basket, relation, stockNames, sourceSession));
        }
      }
    }
  }

  const directionByStock = new Map<string, Set<USPeerDirection>>();
  for (const observation of observations) {
    const directions = directionByStock.get(observation.hkSymbol) || new Set<USPeerDirection>();
    directions.add(observation.direction);
    directionByStock.set(observation.hkSymbol, directions);
  }
  const mixedStockCount = [...directionByStock.values()]
    .filter(directions => directions.has("positive") && directions.has("negative")).length;
  for (const observation of observations) {
    const directions = directionByStock.get(observation.hkSymbol) || new Set<USPeerDirection>();
    observation.hasMixedStockDirection = directions.has("positive") && directions.has("negative");
    observation.stockDirectionLabel = stockDirectionLabel(directions);
  }

  const partition = (direction: USPeerListName) => observations.filter(item => item.direction === direction);
  return {
    sourceSession,
    targetDate,
    formalTargetEligibility,
    acceptedRelationCount,
    mixedStockCount,
    observations,
    positive: partition("positive"),
    negative: partition("negative"),
    flat: partition("flat"),
    unknown: partition("unknown")
  };
}
