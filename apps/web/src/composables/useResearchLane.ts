// Shared derivation helpers for the research decision-desk components.
import { computed, type ComputedRef, type Ref } from "vue";

import type { ResearchLane } from "../api/research_lane";

import { sortFeedCardsByFetchedAt, text } from "./researchFeedPresentation";

export {
  feedCardKey,
  feedFetchTimeLabel,
  feedPublishedTimeLabel,
  fetchedAt,
  fetchedAtField,
  financeOriginalUrl,
  formatFeedTimestamp,
  publishedAt,
  safeExternalUrl,
  sortFeedCardsByFetchedAt,
  text,
  timestampMs,
} from "./researchFeedPresentation";

export function num(value: unknown, fallback = 0): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

export type ResearchCountPresentation = number | "未评估" | "未生成";

/** One payload-bound view model for the status strip; source counts stay distinct. */
export interface ResearchStatusPresentation {
  newItemCount: ResearchCountPresentation;
  zsxqTopicCount: number;
  ocr: string;
  externalFinanceCount: ResearchCountPresentation;
  aiNewsCount: ResearchCountPresentation;
  wechatArticleCount: number;
  stockMainlineLength: number;
  stockTimelineLength: number;
  keyMessagesCount: ResearchCountPresentation;
  hourlySlotCount: number;
}

function statusRecord(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

const AI_DISCOVERY_ONLY_REASON = "AIHOT_PUBLIC_PAGE_DISCOVERY_ONLY";
const KEY_MESSAGES_NOT_MATERIALIZED_REASON = "LANE_PERIPHERAL_NOT_MATERIALIZED:key_investment_messages";

function hasReasonCode(value: unknown, code: string): boolean {
  if (!Array.isArray(value)) return false;
  return value.some((item) => {
    if (typeof item === "string") return item === code;
    const itemRecord = statusRecord(item);
    return [itemRecord.code, itemRecord.reason, itemRecord.description]
      .some((candidate) => text(candidate) === code);
  });
}

function keyMessagesNotMaterialized(payload: ResearchLane): boolean {
  const messages = payload.key_investment_messages;
  return (!Array.isArray(messages) || messages.length === 0)
    && hasReasonCode(payload.cannot_confirm, KEY_MESSAGES_NOT_MATERIALIZED_REASON);
}

function aiReadyEmptyMessage(ai: Record<string, unknown>): string {
  const items = Array.isArray(ai.items) ? ai.items : [];
  if (text(ai.status).toUpperCase() !== "READY_EMPTY" || ai.item_count !== 0 || items.length !== 0) return "";
  if (hasReasonCode(ai.cannot_confirm, AI_DISCOVERY_ONLY_REASON)) {
    return `AI 新闻 0 条；当前无可展示文章。仅公开页面发现，内容完整性无法确认（${AI_DISCOVERY_ONLY_REASON}）。`;
  }
  return "AI 新闻 0 条；当前无可展示文章（READY_EMPTY）。";
}

function assessedCount(value: unknown): ResearchCountPresentation {
  return typeof value === "number" && Number.isFinite(value) && Number.isInteger(value) && value >= 0
    ? value
    : "未评估";
}

function ocrStatusText(ocr: Record<string, unknown>): string {
  const status = String(ocr.status ?? "").trim().toUpperCase();
  const labels: Record<string, string> = {
    READY: "已完成",
    PARTIAL: "部分完成",
    INCOMPLETE: "未完成",
    NOT_ASSESSED: "未评估",
    NOT_MATERIALIZED: "未生成",
    CANNOT_CONFIRM: "无法确认",
    UNKNOWN: "未知",
  };
  const statusLabel = labels[status] ?? status;
  if (["NOT_ASSESSED", "NOT_MATERIALIZED", "CANNOT_CONFIRM", "UNKNOWN"].includes(status)) {
    return statusLabel;
  }
  if (Number.isInteger(ocr.done_count) && Number.isInteger(ocr.failed_count)) {
    const counts = `${num(ocr.done_count)}/${num(ocr.failed_count)}`;
    return statusLabel ? `${statusLabel} · ${counts}` : counts;
  }
  return statusLabel || "未评估";
}

/** Convert one lane payload and its existing derived counts into a reactive consumer-friendly shape. */
export function researchStatusPresentation(
  payload: ResearchLane,
  counts: Pick<ResearchStatusPresentation, "wechatArticleCount" | "stockMainlineLength" | "stockTimelineLength">,
): ResearchStatusPresentation {
  const quality = statusRecord(payload.research_quality_summary);
  const zsxq = statusRecord(payload.zsxq_hourly);
  const ai = statusRecord(payload.ai_news);
  const finance = statusRecord(payload.external_finance);
  const ocr = statusRecord(payload.ocr_ingestion);
  const hourly = statusRecord(payload.hourly_research);

  return {
    newItemCount: assessedCount(quality.new_item_count),
    zsxqTopicCount: num(zsxq.topic_count ?? zsxq.zsxq_topic_count_0800_0900),
    ocr: ocrStatusText(ocr),
    externalFinanceCount: assessedCount(finance.raw_item_count),
    aiNewsCount: assessedCount(ai.item_count),
    wechatArticleCount: counts.wechatArticleCount,
    stockMainlineLength: counts.stockMainlineLength,
    stockTimelineLength: counts.stockTimelineLength,
    keyMessagesCount: keyMessagesNotMaterialized(payload)
      ? "未生成"
      : Array.isArray(payload.key_investment_messages)
        ? payload.key_investment_messages.length
        : "未评估",
    hourlySlotCount: num(hourly.slot_count),
  };
}

const LABELS: Record<string, string> = {
  L3_STRONG: "L3 强证据",
  L2_MEDIUM: "增强证据",
  L1_WEAK: "L1 弱证据",
  RESEARCH_ONLY: "只读研究",
  RESEARCH_FORMAL_OVERLAY: "正式池解释",
  RESEARCH_ONLY_OBSERVE: "研究观察",
  RESEARCH_EVIDENCE_REJECTED: "弱证据拒绝",
  FORMAL_OVERLAY_OK: "正式覆盖",
  OBSERVE_ONLY: "仅观察",
  REJECT_WEAK_EVIDENCE: "弱证据拒绝",
  fresh_24h: "24小时新鲜",
  stored: "历史留存",
};

export function deskText(value: unknown): string {
  return LABELS[text(value)] ?? (text(value) || "-");
}

export function chipList(row: Record<string, unknown>): Array<string> {
  const chips: Array<string> = [];
  const ev = text(row.evidence_level);
  if (ev) chips.push(deskText(ev));
  const evCount = num(row.evidence_count);
  if (evCount > 0) chips.push(`证据 ${evCount}`);
  const score = num(row.research_score);
  if (score > 0) chips.push(`分数 ${score}`);
  const themes = row.themes;
  if (Array.isArray(themes)) chips.push(...(themes as Array<unknown>).slice(0, 3).map((t) => text(t)));
  return chips.slice(0, 6);
}

export function stockTitle(row: Record<string, unknown>): string {
  return [text(row.stock_name || row.name), text(row.stock_code || row.code)].filter(Boolean).join(" ");
}

export type LaneRow = Record<string, unknown> & { _timeline?: Array<Record<string, unknown>> };

/** Group stock_research_timeline by stock_code, merging duplicate same-source events. */
export function timelineByStock(
  stockTimeline: Array<Record<string, unknown>>,
): Map<string, Array<Record<string, unknown>>> {
  const groups = new Map<string, Array<Record<string, unknown>>>();
  for (const event of stockTimeline) {
    const code = text(event.stock_code || event.code);
    if (!code) continue;
    const list = groups.get(code) ?? [];
    list.push(event);
    groups.set(code, list);
  }
  return groups;
}

/** Compact stock timeline events: merge duplicates by (stock, source title, url, source). */
export function compactTimeline(rows: Array<Record<string, unknown>>): Array<Record<string, unknown>> {
  const merged = new Map<string, Record<string, unknown>>();
  for (const event of rows) {
    const key = [
      text(event.stock_code || event.code),
      text(event.source_title || event.title),
      text(event.url || event.source_url),
      text(event.source_name || event.source_type),
      text(event.claim_type || event.evidence_level),
    ].join("|").toLowerCase();
    if (!key) continue;
    const existing = merged.get(key);
    if (!existing) {
      merged.set(key, { ...event, duplicate_evidence_count: 1 });
      continue;
    }
    existing.duplicate_evidence_count = (num(existing.duplicate_evidence_count) || 0) + 1;
    if (text(event.evidence_sentence).length > text(existing.evidence_sentence).length) {
      existing.evidence_sentence = event.evidence_sentence;
    }
  }
  return Array.from(merged.values());
}

export interface ResearchState {
  payload: Ref<ResearchLane | null>;
  stockDaily: ComputedRef<Array<Record<string, unknown>>>;
  stockTimeline: ComputedRef<Array<Record<string, unknown>>>;
  quality: ComputedRef<Record<string, unknown>>;
  morning: ComputedRef<Record<string, unknown>>;
  workbench: ComputedRef<Record<string, unknown>>;
  zsxq: ComputedRef<Record<string, unknown>>;
  ai: ComputedRef<Record<string, unknown>>;
  finance: ComputedRef<Record<string, unknown>>;
  gaps: ComputedRef<Array<unknown>>;
  stockMainline: ComputedRef<Array<LaneRow>>;
  feedCards: ComputedRef<Array<Record<string, unknown>>>;
  feedEmptyMessage: ComputedRef<string>;
  sourceColumns: ComputedRef<Array<{ name: string; rows: Array<Record<string, unknown>>; emptyMessage?: string }>>;
  timelineRows: ComputedRef<Array<Record<string, unknown>>>;
  cannotItems: ComputedRef<Array<string>>;
}

export function useResearchState(payload: Ref<ResearchLane | null>, feedFilter: Ref<string>): ResearchState {
  const stockDaily = computed(() => (payload.value?.stock_research_daily ?? []) as Array<Record<string, unknown>>);
  const stockTimeline = computed(() => (payload.value?.stock_research_timeline ?? []) as Array<Record<string, unknown>>);
  const quality = computed(() => payload.value?.research_quality_summary ?? {});
  const morning = computed(() => payload.value?.morning_news ?? {});
  const workbench = computed(() => payload.value?.news_workbench ?? {});
  const zsxq = computed(() => payload.value?.zsxq_hourly ?? {});
  const ai = computed(() => payload.value?.ai_news ?? {});
  const finance = computed(() => payload.value?.external_finance ?? {});
  const gaps = computed(() => (payload.value?.cannot_confirm ?? []) as Array<unknown>);

  const stockMainline = computed<Array<LaneRow>>(() => {
    const byStock = timelineByStock(stockTimeline.value);
    return stockDaily.value.slice(0, 8).map((row) => ({
      ...row,
      _timeline: compactTimeline(byStock.get(text(row.stock_code || row.code)) ?? []).slice(0, 3),
    }));
  });

  const feedCards = computed(() => {
    const articles = (morning.value.articles ?? []) as Array<Record<string, unknown>>;
    const actionRows = (workbench.value.action_rows ?? []) as Array<Record<string, unknown>>;
    const aiItems = Array.isArray(ai.value.items) ? (ai.value.items as Array<Record<string, unknown>>) : [];
    const financeOverview = Array.isArray(finance.value.overview)
      ? (finance.value.overview as Array<Record<string, unknown>>)
      : [];
    const zsxqItems = Array.isArray(zsxq.value.items) ? (zsxq.value.items as Array<Record<string, unknown>>) : [];
    const keyMessages = Array.isArray(payload.value?.key_investment_messages)
      ? (payload.value.key_investment_messages as Array<Record<string, unknown>>)
      : [];
    const cards: Array<Record<string, unknown>> = [];
    for (const row of articles) cards.push({ ...row, kind: "article", feed_source: "morning" });
    for (const row of actionRows) cards.push({ ...row, kind: "workbench", source: "workbench" });
    for (const row of aiItems) cards.push({ ...row, kind: "ai", source: "ai" });
    for (const row of financeOverview) cards.push({ ...row, kind: "finance", source: "finance" });
    for (const row of zsxqItems) cards.push({ ...row, kind: "zsxq", source: "zsxq" });
    for (const row of keyMessages) cards.push({ ...row, kind: "key", source: "key" });
    const byFilter: Record<string, Array<Record<string, unknown>>> = {
      latest: cards,
      morning: cards.filter((c) => c.kind === "article"),
      stock: cards.filter((c) => text(c.stock_code || c.stock_name)),
      zsxq: cards.filter((c) => c.source === "zsxq"),
      finance: cards.filter((c) => c.source === "finance"),
      ai: cards.filter((c) => c.source === "ai"),
      key: cards.filter((c) => c.source === "key"),
    };
    const selected = byFilter[feedFilter.value] ?? cards;
    return feedFilter.value === "latest"
      ? sortFeedCardsByFetchedAt(selected)
      : selected;
  });

  const feedEmptyMessage = computed(() => {
    if (feedCards.value.length === 0 && feedFilter.value === "ai") {
      return aiReadyEmptyMessage(ai.value) || "当前情报日无 feed 条目。";
    }
    if (feedCards.value.length === 0 && feedFilter.value === "key" && payload.value && keyMessagesNotMaterialized(payload.value)) {
      return `重点消息未生成（${KEY_MESSAGES_NOT_MATERIALIZED_REASON}）。`;
    }
    return "当前情报日无 feed 条目。";
  });

  const sourceColumns = computed(() => {
    const aiItems = Array.isArray(ai.value.items) ? ai.value.items as Array<Record<string, unknown>> : [];
    const columns: Array<{ name: string; rows: Array<Record<string, unknown>>; emptyMessage?: string }> = [
      { name: "知识星球", rows: (Array.isArray(zsxq.value.items) ? zsxq.value.items as Array<Record<string, unknown>> : []).slice(0, 8) },
      { name: "外部财经", rows: (Array.isArray(finance.value.overview) ? finance.value.overview as Array<Record<string, unknown>> : []).slice(0, 8) },
      { name: "AI新闻", rows: aiItems.slice(0, 8), emptyMessage: aiReadyEmptyMessage(ai.value) },
    ];
    const morningArticles = (morning.value.articles ?? []) as Array<Record<string, unknown>>;
    if (morningArticles.length) columns.push({ name: "早盘新闻", rows: morningArticles.slice(0, 8) });
    return columns;
  });

  const timelineRows = computed<Array<Record<string, unknown>>>(() =>
    compactTimeline(stockTimeline.value).slice(0, 30).map((row) => ({
      ...row,
      _time: text(row.event_time).slice(11, 16),
    })),
  );

  const cannotItems = computed(() => gaps.value.map((item) => {
    if (typeof item === "string") return item;
    const rec = item as Record<string, unknown>;
    return text(rec.description || rec.reason || item);
  }));

  return {
    payload, stockDaily, stockTimeline, quality, morning, workbench, zsxq, ai, finance, gaps,
    stockMainline, feedCards, feedEmptyMessage, sourceColumns, timelineRows, cannotItems,
  };
}
