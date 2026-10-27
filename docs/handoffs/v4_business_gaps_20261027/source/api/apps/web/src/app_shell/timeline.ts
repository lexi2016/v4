import type { StageDefinition } from "./types";
import type { ClosingTimelineNode, TaskStatusResponse } from "../contracts/runtime";

export function createTimeline() {

const stageDefinitions: StageDefinition[] = [
  { id: "STAGE_0925", label: "港股通09:20 / A股09:25竞价选股", timeline: "1. 港股通09:20 / A股09:25竞价选股" },
  { id: "STAGE_0930_0935", label: "09:30-09:35", timeline: "2. 09:30-09:35" },
  { id: "STAGE_0935_0940", label: "09:35-09:40", timeline: "3. 09:35-09:40" },
  { id: "STAGE_0940_0945", label: "09:40-09:45", timeline: "4. 09:40-09:45" },
  { id: "STAGE_0945_1030", label: "09:45-10:30", timeline: "5. 09:45-10:30" },
  { id: "STAGE_1300_1315", label: "13:00-13:15", timeline: "6. 13:00-13:15" },
  { id: "STAGE_1445_1500", label: "14:45-15:00", timeline: "7. 14:45-15:00" },
  { id: "STAGE_1545_1555", label: "15:45-15:55港股", timeline: "8. 15:45-15:55港股" },
];
const closingTimeline: ClosingTimelineNode[] = [
  { node_id: "hkconnect_model_selection_review", label: "9. 16:10 港股通正式收盘：0.2 × 七阶段 Top20", owner_id: "v35_dispatcher.hk_connect_close_review" },
  { node_id: "FUPAN_CLOSE_MATERIALS", label: "10. 15:00 收盘前总结材料", owner_id: "v35_dispatcher.fupan_close_materials" },
  { node_id: "FUPAN_REVIEW_START", label: "11. 15:55 收盘后复盘启动", owner_id: "v35_dispatcher.fupan_review_start" },
  { node_id: "FUPAN_A_SHARE_STRUCTURE", label: "12. 16:05 A股收盘数据与题材骨架", owner_id: "v35_dispatcher.a_share_close_review" },
  { node_id: "FUPAN_VIDEO_CHECK", label: "13. 20:30 最新复盘视频检查", owner_id: "v35_dispatcher.fupan_video_check" },
  { node_id: "FUPAN_VIDEO_DOWNLOAD_ASR", label: "14. 20:40 视频下载与转写", owner_id: "v35_dispatcher.fupan_video_download_asr" },
  { node_id: "FUPAN_STOCKDICT", label: "15. 20:50 股票字典校正", owner_id: "v35_dispatcher.fupan_stockdict" },
  { node_id: "FUPAN_VIDEO_TABLE_OCR_ALIGN", label: "16. 21:05 视频表格OCR/ASR/新闻对齐", owner_id: "v35_dispatcher.fupan_video_table_ocr_align" },
  { node_id: "FUPAN_VIDEO_GAP", label: "17. 21:08 页面复盘对视频差距", owner_id: "v35_dispatcher.fupan_video_gap" },
  { node_id: "FUPAN_V3_PUBLISH", label: "18. 21:10 第三版复盘发布", owner_id: "v35_dispatcher.fupan_v3_publish" },
  { node_id: "FUPAN_8771_VERIFY", label: "19. 21:15 8873 页面与接口验收", owner_id: "v35_dispatcher.fupan_8873_verify" },
];
  return { stageDefinitions, closingTimeline };
}

const TASK_STATES = new Set(["PLANNED", "QUEUED", "RUNNING", "WAITING_DEPENDENCY", "FAILED", "PARTIAL", "READY", "CANNOT_CONFIRM"]);

export function projectClosingTimeline(
  definitions: ClosingTimelineNode[], payload: TaskStatusResponse | null, date: string,
) {
  return definitions.map((definition) => {
    const matches = payload?.business_date === date
      ? (payload.timeline_nodes ?? []).filter((node) => node.node_id === definition.node_id && node.owner_id === definition.owner_id && node.business_date === date)
      : [];
    const node = matches.length === 1 ? matches[0] : undefined;
    let state = node && TASK_STATES.has(node.task_state ?? "") ? node.task_state! : "CANNOT_CONFIRM";
    if (state === "READY" && (!node?.run_id || node.binding_status !== "BUSINESS_RECEIPT_BOUND_TO_DISPATCH_RUN")) state = "CANNOT_CONFIRM";
    return {
      ...definition,
      label: node?.label ? `${node.position}. ${node.label}` : definition.label,
      state,
      reason: node?.reason || "无该日期的可验证任务回执",
      run_id: node?.run_id || "CANNOT_CONFIRM",
      binding_status: node?.binding_status || "CANNOT_CONFIRM",
      receipt_path: node?.actual_receipt_path || "",
    };
  });
}

// Refresh once at the next plan boundary. No minute polling or producer call.
export function nextClosingStatusDelay(payload: TaskStatusResponse, date: string, now = Date.now()): number | null {
  if (payload.business_date !== date || !/^\d{8}$/.test(date)) return null;
  const currentDate = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(now)).replaceAll("-", "");
  if (date !== currentDate) return null;
  const due = (payload.timeline_nodes ?? [])
    .filter((node) => node.position > 8 && node.business_date === date && node.task_state === "PLANNED" && /^\d{4}$/.test(node.planned_time ?? ""))
    .map((node) => {
      const slot = node.planned_time!;
      return Date.parse(`${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6,8)}T${slot.slice(0,2)}:${slot.slice(2)}:00+08:00`);
    }).filter((time) => time > now);
  return due.length ? Math.min(...due) - now + 1000 : null;
}
