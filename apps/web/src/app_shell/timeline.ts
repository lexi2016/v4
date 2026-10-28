import type { StageDefinition } from "./types";

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
const closingTimeline = [
  "9. 16:10 港股通正式收盘：0.2 × 七阶段 Top20",
  "10. 15:00 收盘前总结材料",
  "11. 15:55 收盘后复盘启动",
  "12. 16:05 A股收盘数据与题材骨架",
  "13. 20:30 最新复盘视频检查",
  "14. 20:40 视频下载与转写",
  "15. 20:50 股票字典校正",
  "16. 21:05 视频表格OCR/ASR/新闻对齐",
  "17. 21:08 页面复盘对视频差距",
  "18. 21:10 第三版复盘发布",
  "19. 21:15 8871 刷新与页面验收",
];
  return { stageDefinitions, closingTimeline };
}
