/** Shared timestamp and source presentation for research feed cards. */
export function text(value: unknown): string {
  return String(value ?? "").trim();
}

const FETCH_TIME_FIELDS = ["fetched_at", "collected_at", "first_seen_at", "published_at"] as const;
type FetchTimeField = (typeof FETCH_TIME_FIELDS)[number];

const ISO_TIMESTAMP_WITH_EXPLICIT_OFFSET = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?\s*(?:Z|[+-]\d{2}:\d{2})$/;
const ISO_TIMESTAMP_WITHOUT_OFFSET = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?$/;

function validTimestamp(value: unknown): string {
  const raw = text(value);
  if (!raw || !ISO_TIMESTAMP_WITH_EXPLICIT_OFFSET.test(raw) || !Number.isFinite(Date.parse(raw))) return "";
  return raw;
}

export function fetchedAt(row: Record<string, unknown>): string {
  for (const field of FETCH_TIME_FIELDS) {
    const value = validTimestamp(row[field]);
    if (value) return value;
  }
  return "";
}

export function fetchedAtField(row: Record<string, unknown>): FetchTimeField | "" {
  for (const field of FETCH_TIME_FIELDS) {
    if (validTimestamp(row[field])) return field;
  }
  return "";
}

export function publishedAt(row: Record<string, unknown>): string {
  for (const field of ["published_at", "source_published_at", "publication_time"] as const) {
    const value = validTimestamp(row[field]);
    if (value) return value;
  }
  return "";
}

export function timestampMs(value: unknown): number {
  const raw = validTimestamp(value);
  if (!raw) return Number.NEGATIVE_INFINITY;
  const parsed = Date.parse(raw);
  return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
}

export function formatFeedTimestamp(value: unknown): string {
  const raw = validTimestamp(value);
  if (!raw) return "";
  return raw.replace("T", " ").replace(/\.\d+(?=(?:Z|[+-]\d\d:\d\d)?$)/, "");
}

const FETCH_TIME_LABELS: Record<FetchTimeField, string> = {
  fetched_at: "抓取时间",
  collected_at: "采集时间",
  first_seen_at: "首次发现",
  published_at: "原文发布时间",
};

export function feedFetchTimeLabel(row: Record<string, unknown>): string {
  const value = fetchedAt(row);
  const field = fetchedAtField(row);
  if (!value || !field) {
    const captureFields = ["fetched_at", "collected_at", "first_seen_at"] as const;
    const hasCaptureTimeEvidence = captureFields.some((captureField) => text(row[captureField]));
    const reason = hasCaptureTimeEvidence
      ? "来源提供的采集时间字段无法核验"
      : "来源未提供抓取/采集时间字段";
    return `获取时间：CANNOT_CONFIRM（${reason}）`;
  }
  const rendered = formatFeedTimestamp(value) || value;
  if (field === "fetched_at") return `获取时间：${rendered}`;
  return `获取时间：${rendered}（回退自${FETCH_TIME_LABELS[field]}；实际抓取时间 CANNOT_CONFIRM）`;
}

export function feedPublishedTimeLabel(row: Record<string, unknown>): string {
  const value = publishedAt(row);
  if (value) return `原文时间：${formatFeedTimestamp(value) || value}`;
  for (const field of ["published_at", "source_published_at", "publication_time"] as const) {
    const raw = text(row[field]);
    if (!raw) continue;
    const reason = ISO_TIMESTAMP_WITHOUT_OFFSET.test(raw)
      ? "原始时间字段未提供时区，无法核验"
      : "原始时间字段格式无法核验";
    return `原文时间：CANNOT_CONFIRM（${reason}）；原始字段 ${field}=${raw.slice(0, 120)}`;
  }
  return "原文时间：CANNOT_CONFIRM（来源未提供可核验的原文时间字段）";
}

export function feedCardKey(row: Record<string, unknown>, index = 0): string {
  return text(row.article_id || row.evidence_id || row.item_id || row.id || row.url || row.title || index);
}

export function sortFeedCardsByFetchedAt(rows: Array<Record<string, unknown>>): Array<Record<string, unknown>> {
  return rows
    .map((card, index) => ({ card, index, key: feedCardKey(card, index) }))
    .sort((left, right) => {
      const rightMs = timestampMs(fetchedAt(right.card));
      const leftMs = timestampMs(fetchedAt(left.card));
      if (rightMs !== leftMs) return rightMs - leftMs;
      const rightHasTime = Boolean(fetchedAt(right.card));
      const leftHasTime = Boolean(fetchedAt(left.card));
      if (rightHasTime !== leftHasTime) return rightHasTime ? 1 : -1;
      return left.key.localeCompare(right.key) || left.index - right.index;
    })
    .map(({ card }) => card);
}

export function safeExternalUrl(raw: unknown): string {
  if (typeof raw !== "string" || !raw.trim()) return "";
  let parsed: URL;
  try {
    parsed = new URL(raw.trim());
  } catch {
    return "";
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return "";
  if (!parsed.hostname || parsed.username || parsed.password) return "";
  return parsed.href;
}

export function financeOriginalUrl(row: Record<string, unknown>): string {
  for (const field of ["original_url", "source_url"] as const) {
    const safe = safeExternalUrl(row[field]);
    if (safe) return safe;
  }
  return "";
}

export interface FeedCardPresentation {
  categoryClass: string;
  sourceLabel: string;
  typeLabel: string;
  showTypeLabel: boolean;
  fetchedTimeLabel: string;
  publishedTimeLabel: string;
}

export function feedCardPresentation(row: Record<string, unknown>): FeedCardPresentation {
  const rawSource = text(row.source);
  const sourceType = text(row.source_type);
  const category = text(row.feed_source || row.kind || sourceType || rawSource);
  const typeLabel = category === "morning" || category === "article" ? "早盘" : category;
  const sourceLabel = text(row.source_name)
    || (rawSource && rawSource !== category ? rawSource : "")
    || (sourceType && sourceType !== category ? sourceType : "")
    || typeLabel;

  return {
    categoryClass: category,
    sourceLabel,
    typeLabel,
    showTypeLabel: Boolean(typeLabel && typeLabel !== sourceLabel),
    fetchedTimeLabel: feedFetchTimeLabel(row),
    publishedTimeLabel: feedPublishedTimeLabel(row),
  };
}
