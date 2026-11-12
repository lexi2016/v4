// Shared derivation helpers for the research decision-desk components.
import { computed, type ComputedRef, type Ref } from "vue";

import type { ResearchLane } from "../api/research_lane";

export function text(value: unknown): string {
  return String(value ?? "").trim();
}

/** Return only an absolute, credential-free HTTP(S) URL suitable for an external link. */
export function safeExternalUrl(raw: unknown): string {
  if (typeof raw !== "string" || !raw.trim() || !/^(?:https?):\/\//i.test(raw.trim())) return "";
  let parsed: URL;
  try {
    // Do not provide a base URL: protocol-relative and relative values must fail closed.
    parsed = new URL(raw.trim());
  } catch {
    return "";
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return "";
  if (!parsed.hostname || parsed.username || parsed.password) return "";
  return parsed.href;
}

export const UNKNOWN_STOCK_NAME = "股票名称不可确认";

export function stockName(row: Record<string, unknown>): string {
  return text(row.stock_name) || text(row.name) || UNKNOWN_STOCK_NAME;
}

export function stockCode(row: Record<string, unknown>): string {
  return text(row.stock_code) || text(row.code);
}

export function stockDisplayTitle(row: Record<string, unknown>): string {
  const knownName = text(row.stock_name) || text(row.name);
  return knownName || text(row.title) || text(row.content) || UNKNOWN_STOCK_NAME;
}

export function financeTitle(row: Record<string, unknown>): string {
  return text(row.title_zh) || text(row.title);
}

export function financeSummary(row: Record<string, unknown>): string {
  return text(row.summary_zh) || text(row.summary);
}

/** External finance sources expose original_url first, then source_url as a safe fallback. */
export function financeOriginalUrl(row: Record<string, unknown>): string {
  for (const field of ["original_url", "source_url"] as const) {
    const safe = safeExternalUrl(row[field]);
    if (safe) return safe;
  }
  return "";
}

export function financeSourceUrl(row: Record<string, unknown>): string {
  return financeOriginalUrl(row);
}

export function financeOriginalTitle(row: Record<string, unknown>): string {
  return text(row.title);
}

export function num(value: unknown, fallback = 0): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
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
  return [stockName(row), stockCode(row)].filter(Boolean).join(" ");
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
      text(event.source_url) || text(event.original_url),
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
  financeRows: ComputedRef<Array<Record<string, unknown>>>;
  gaps: ComputedRef<Array<unknown>>;
  stockMainline: ComputedRef<Array<LaneRow>>;
  feedCards: ComputedRef<Array<Record<string, unknown>>>;
  sourceColumns: ComputedRef<Array<{ name: string; rows: Array<Record<string, unknown>> }>>;
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
  const financeRows = computed<Array<Record<string, unknown>>>(() => {
    const details = Array.isArray(finance.value.details)
      ? finance.value.details as Array<Record<string, unknown>>
      : [];
    if (details.length) return details;
    return Array.isArray(finance.value.overview)
      ? finance.value.overview as Array<Record<string, unknown>>
      : [];
  });
  const gaps = computed(() => (payload.value?.cannot_confirm ?? []) as Array<unknown>);

  const stockMainline = computed<Array<LaneRow>>(() => {
    const byStock = timelineByStock(stockTimeline.value);
    return stockDaily.value.slice(0, 8).map((row) => ({
      ...row,
      stock_name: stockName(row),
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
    const financeFeedRows = feedFilter.value === "finance" ? financeRows.value : financeOverview;
    const zsxqItems = Array.isArray(zsxq.value.items) ? (zsxq.value.items as Array<Record<string, unknown>>) : [];
    const keyMessages = Array.isArray(payload.value?.key_investment_messages)
      ? (payload.value.key_investment_messages as Array<Record<string, unknown>>)
      : [];
    const cards: Array<Record<string, unknown>> = [];
    for (const row of articles) cards.push({ kind: "article", source: "morning", ...row });
    for (const row of actionRows) cards.push({ kind: "workbench", source: "workbench", ...row });
    for (const row of aiItems) cards.push({ kind: "ai", source: "ai", ...row });
    for (const row of financeFeedRows) cards.push({ kind: "finance", ...row, source: "finance" });
    for (const row of zsxqItems) cards.push({ kind: "zsxq", source: "zsxq", ...row });
    for (const row of keyMessages) cards.push({ kind: "key", source: "key", ...row });
    const byFilter: Record<string, Array<Record<string, unknown>>> = {
      latest: cards,
      stock: cards.filter((c) => text(c.stock_code || c.stock_name)),
      zsxq: cards.filter((c) => c.source === "zsxq"),
      finance: cards.filter((c) => c.source === "finance"),
      ai: cards.filter((c) => c.source === "ai"),
      key: cards.filter((c) => c.source === "key"),
    };
    return (byFilter[feedFilter.value] ?? cards).slice(0, 42);
  });

  const sourceColumns = computed(() => {
    const columns: Array<{ name: string; rows: Array<Record<string, unknown>> }> = [
      { name: "知识星球", rows: (Array.isArray(zsxq.value.items) ? zsxq.value.items as Array<Record<string, unknown>> : []).slice(0, 8) },
      { name: "外部财经", rows: financeRows.value },
      { name: "AI新闻", rows: (Array.isArray(ai.value.items) ? ai.value.items as Array<Record<string, unknown>> : []).slice(0, 8) },
    ];
    const morningArticles = (morning.value.articles ?? []) as Array<Record<string, unknown>>;
    if (morningArticles.length) columns.push({ name: "早盘新闻", rows: morningArticles.slice(0, 8) });
    return columns;
  });

  const timelineRows = computed<Array<Record<string, unknown>>>(() =>
    compactTimeline(stockTimeline.value).slice(0, 30).map((row) => ({
      ...row,
      stock_name: stockName(row),
      _time: text(row.event_time).slice(11, 16),
    })),
  );

  const cannotItems = computed(() => gaps.value.map((item) => {
    if (typeof item === "string") return item;
    const rec = item as Record<string, unknown>;
    return text(rec.description || rec.reason || item);
  }));

  return {
    payload, stockDaily, stockTimeline, quality, morning, workbench, zsxq, ai, finance, financeRows, gaps,
    stockMainline, feedCards, sourceColumns, timelineRows, cannotItems,
  };
}
