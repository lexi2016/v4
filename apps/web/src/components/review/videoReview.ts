type Row = Readonly<Record<string, unknown>>;

// Local display contract for the verified, read-only raw ASR projection.
interface TranscriptSegment {
  segment_id: string;
  start_seconds: number;
  end_seconds: number;
  text: string;
  evidence_status: "ASR_UNVERIFIED";
  source_sha256: string;
}

export function record(value: unknown): Row {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Row : {};
}

export function text(row: Row, ...keys: string[]): string {
  for (const key of keys) {
    const value = row[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

export function videoBv(value: unknown): string {
  return typeof value === "string" && /^BV[1-9A-HJ-NP-Za-km-z]{10}$/.test(value) ? value : "";
}

export function timestampSeconds(value: unknown): number | null {
  if (typeof value === "number") return Number.isSafeInteger(value) && value >= 0 ? value : null;
  if (typeof value !== "string") return null;
  const timestamp = value.trim();
  if (/^\d+$/.test(timestamp)) return timestampSeconds(Number(timestamp));
  const parts = timestamp.match(/^(\d+):([0-5]\d)(?::([0-5]\d))?$/);
  if (!parts) return null;
  const seconds = parts[3] === undefined
    ? Number(parts[1]) * 60 + Number(parts[2])
    : Number(parts[1]) * 3600 + Number(parts[2]) * 60 + Number(parts[3]);
  // In HH:MM:SS, the middle component must be a minute within the hour.
  return timestampSeconds(seconds);
}

export function timestampLabel(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor(seconds % 3600 / 60);
  const tail = `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  return hours ? `${hours}:${tail}` : tail;
}

function count(value: unknown): string {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? String(value) : "未提供";
}

const STATUS: Record<string, string> = {
  TARGET_BV_LOCKED: "目标视频已锁定",
  CAPTURED: "已采集",
  VIDEO_GAP_AUDIT_EMPTY: "尚无逐条对照记录",
  DAILY_VIDEO_NOT_LOCKED: "当天视频未锁定",
  ASR_REVIEW_REQUIRED: "转写待复核",
  ASR_SEGMENT_SPOTCHECK_REQUIRED: "片段待抽查",
  ASR_READY: "转写已生成（结论仍需核对）",
  READY: "材料已就绪（不代表内容确认）",
  VIDEO_GAP_AUDIT_READY: "差距审计材料已生成",
  VIDEO_GAP_AUDIT_PARTIAL: "差距审计材料不完整",
  LOCAL_REVIEW_HAS_OUTPUT: "本地已有输出（未验证语义一致）",
  LOCAL_REVIEW_WEAK_OR_MISSING: "本地材料薄弱或缺失",
  NO_ACTION: "未标记改进项（不代表分析通过）",
  BLOCKED: "受阻",
  CANNOT_CONFIRM: "无法确认",
  NOT_MATERIALIZED: "尚未生成",
  ASR_STOCKDICT_OBSERVATION_READY: "股票词典命中（仅观察证据）",
};

export function videoStatusLabel(value: string): string {
  return STATUS[value] || value || "未提供";
}

function exactScope(row: Row, date: string, bv: string): boolean {
  return ["trade_date", "target_trade_date", "review_date"].every((key) => (
    row[key] === undefined || row[key] === null || row[key] === "" || row[key] === date
  )) && (row.bv_id === undefined || row.bv_id === null || row.bv_id === "" || row.bv_id === bv);
}

function scopedRows(value: unknown, date: string, bv: string): Row[] {
  if (!Array.isArray(value)) return [];
  return value.filter((value) => (
    value !== null && typeof value === "object" && !Array.isArray(value)
    && exactScope(value as Row, date, bv)
  ));
}

function transcriptProblem(value: unknown, date: string, bv: string, sha: string): string {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return "分段结构无效";
  const row = value as Row;
  if (!exactScope(row, date, bv)) return "日期或 BV 与当天来源不一致";
  if (typeof row.segment_id !== "string" || !row.segment_id.trim()) return "缺少分段标识";
  if (typeof row.text !== "string" || !row.text.trim()) return "缺少转写正文";
  if (row.evidence_status !== "ASR_UNVERIFIED") return "证据状态不符合原始转写合同";
  if (row.source_sha256 !== sha) return "来源 SHA 与全文来源不一致";
  if (typeof row.start_seconds !== "number" || !Number.isFinite(row.start_seconds) || row.start_seconds < 0
    || row.start_seconds > Number.MAX_SAFE_INTEGER
    || typeof row.end_seconds !== "number" || !Number.isFinite(row.end_seconds) || row.end_seconds < row.start_seconds
    || row.end_seconds > Number.MAX_SAFE_INTEGER) return "分段时间无效";
  return "";
}

/** Read-only projection of the existing video contract; no source recovery or semantic scoring. */
export function videoReviewView(tradeDate: string, source: unknown, gaps: unknown, learning: unknown) {
  const candidate = record(source);
  const sameDate = /^\d{8}$/.test(tradeDate)
    && candidate.target_trade_date === tradeDate && candidate.trade_date === tradeDate;
  const video = sameDate ? candidate : {};
  const bv = videoBv(video.bv_id);
  const status = text(video, "status");
  const scope = text(video, "date_scope");
  const discovery = text(video, "discovery_status");
  const notLocked = !sameDate || !bv || [status, scope, discovery].some((value) => value.includes("NOT_LOCKED"));
  const canShow = sameDate && !!bv && !notLocked;
  const rows = canShow ? [
    ...scopedRows(gaps, tradeDate, bv).map((row) => ({ row, kind: "视频对照" })),
    ...scopedRows(learning, tradeDate, bv).map((row) => ({ row, kind: "学习记录" })),
  ] : [];
  const asrStatus = text(video, "asr_status");
  const pending = [status, asrStatus, ...rows.flatMap(({ row }) => [text(row, "decision"), text(row, "status")])]
    .some((value) => value.includes("REVIEW_REQUIRED") || value.includes("SPOTCHECK_REQUIRED"));
  const url = canShow ? `https://www.bilibili.com/video/${bv}` : "";
  const cannotConfirm = canShow ? (Array.isArray(video.cannot_confirm)
    ? video.cannot_confirm.filter((value): value is string => typeof value === "string")
    : [text(video, "cannot_confirm")].filter(Boolean)) : [];
  const unusable = video.transcript_usable === false || cannotConfirm.includes("ASR transcript is not usable");
  const contentSource = record(video.content_source);
  const contentSha = text(contentSource, "sha256");
  const contentQuality = record(video.content_quality);
  const contentErrors: string[] = [];
  const rawSegments: unknown[] = Array.isArray(video.transcript_segments) ? video.transcript_segments : [];
  const rawAvailable = canShow && video.content_status === "RAW_ASR_AVAILABLE";
  if (rawAvailable) {
    if (!/^[a-fA-F0-9]{64}$/.test(contentSha)) contentErrors.push("全文来源 SHA 无效");
    if (contentQuality.status !== "ASR_UNVERIFIED") contentErrors.push("全文证据状态不符合原始转写合同");
    if (!Array.isArray(video.transcript_segments)) contentErrors.push("全文分段列表未提供或结构无效");
    for (const [label, declared] of [["来源声明", video.asr_segment_count], ["正文质量记录", contentQuality.segment_count]] as const) {
      if (count(declared) === "未提供") contentErrors.push(`${label}段数未提供或无效`);
      else if (declared !== rawSegments.length) contentErrors.push(`${label}段数 ${declared} 与正文实际 ${rawSegments.length} 段不一致`);
    }
    rawSegments.forEach((value, index) => {
      const problem = transcriptProblem(value, tradeDate, bv, contentSha);
      if (problem) contentErrors.push(`第 ${index + 1} 段：${problem}`);
    });
  }
  // A full transcript is atomic: never filter invalid rows into a partial "full text".
  const transcript = rawAvailable && !contentErrors.length
    ? (rawSegments as TranscriptSegment[]).map((row, index) => ({
      key: `${row.segment_id}-${index}`, text: row.text,
      time: `${timestampLabel(Math.floor(row.start_seconds))}–${timestampLabel(Math.floor(row.end_seconds))}`,
      url: `${url}?t=${Math.floor(row.start_seconds)}`,
    })) : [];
  return {
    sameDate, canShow, bv: canShow ? bv : "", url,
    title: canShow ? text(video, "video_title", "title") || "未提供视频标题" : "未提供当天可核对的视频来源",
    summary: notLocked ? "当天视频未锁定" : [scope, status, discovery].includes("TARGET_BV_LOCKED")
      ? "目标视频已锁定" : "当天视频标识已提供，锁定状态以来源记录为准",
    dateMessage: sameDate ? "来源日期与目标日期一致" : "来源日期缺失或不一致，已隔离视频内容与对照记录。",
    sourceStatus: sameDate ? videoStatusLabel(discovery || status) : "未提供当天来源状态",
    captureStatus: canShow ? videoStatusLabel(text(video, "capture_status")) : "未提供",
    asrStatus: canShow ? videoStatusLabel(asrStatus) : "未提供",
    segments: canShow ? count(video.asr_segment_count) : "未提供",
    usable: canShow && unusable ? "不可用于结论" : canShow && video.transcript_usable === true ? "来源标记可用（结论仍需核对）" : "未提供",
    gapStatus: canShow ? videoStatusLabel(text(video, "gap_status")) : "未提供",
    pending,
    transcript,
    contentMessage: canShow ? text(record(video.content_quality), "message") : "",
    contentSource: transcript.length ? `${text(contentSource, "path") || "未提供路径"} · SHA-256：${contentSha}` : "",
    contentCannotConfirm: canShow ? [
      ...(Array.isArray(video.content_cannot_confirm)
        ? video.content_cannot_confirm.filter((value): value is string => typeof value === "string") : []),
      ...contentErrors,
    ].join("；") : "",
    cannotConfirm: cannotConfirm.join("；"),
    artifacts: canShow ? scopedRows(video.artifact_refs, tradeDate, bv).filter((row) => (
      [text(row, "path"), text(row, "source_path")].every((path) => (
        [...path.matchAll(/(?:^|[\\/])review[\\/](\d{8}|\d{4}-\d{2}-\d{2})(?=[\\/]|$)/g)]
          .every((match) => match[1].replaceAll("-", "") === tradeDate)
      ))
    )).map((row) => ({ kind: text(row, "kind") || "来源工件", path: text(row, "path", "source_path"), sha: text(row, "sha256") })) : [],
    rows: rows.map(({ row, kind }, index) => {
      const seconds = timestampSeconds(row.timestamp);
      return {
        key: `${kind}-${text(row, "row_id", "id")}-${index}`, kind,
        item: text(row, "item", "title_or_segment") || "未提供主题",
        point: text(row, "video_question_or_framework", "video_framework") || "未提供视频观点或框架",
        local: text(row, "current_local_review_behavior", "local_review_answer") || "未提供本地对照",
        gap: text(row, "gap_type") || "未提供",
        status: [...new Set([text(row, "decision"), text(row, "status")].filter(Boolean))].map(videoStatusLabel).join("；") || "未提供",
        quote: text(row, "original_quote", "quote"),
        snippet: text(row, "evidence_snippet"),
        impact: text(row, "impact"),
        cannotConfirm: text(row, "cannot_confirm"),
        evidence: text(row, "evidence_path", "evidence_route"),
        time: seconds === null ? "未提供可靠时间点" : timestampLabel(seconds),
        timeUrl: seconds === null ? "" : `${url}?t=${seconds}`,
      };
    }),
  };
}
