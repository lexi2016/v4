import type { Phase } from "./types";

export interface WorkbenchRoute { date: string; phase: Phase | ""; runId: string; error: string | null }
export const PHASES: Phase[] = ["PREOPEN", "INTRADAY", "NEXT_DAY", "RETROSPECTIVE", "MANUAL"];

export function isValidDate(value: string): boolean {
  if (!/^[0-9]{8}$/.test(value)) return false;
  const y = Number(value.slice(0, 4));
  const m = Number(value.slice(4, 6));
  const d = Number(value.slice(6, 8));
  if (y < 1900 || y > 2100 || m < 1 || m > 12 || d < 1 || d > 31) return false;
  const actual = new Date(Date.UTC(y, m - 1, d));
  return actual.getUTCFullYear() === y && actual.getUTCMonth() === m - 1 && actual.getUTCDate() === d;
}
export function todayHongKong(now = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Hong_Kong", year: "numeric", month: "2-digit", day: "2-digit"
  }).formatToParts(now);
  const take = (type: string) => parts.find(x => x.type === type)?.value || "";
  return take("year") + take("month") + take("day");
}
export function parseWorkbenchRoute(search: string, now = new Date()): WorkbenchRoute {
  const params = new URLSearchParams(search);
  // A historical plan_date, when present, is the target trading day rather than a source-date.
  const date = params.get("plan_date") || params.get("date") || todayHongKong(now);
  const phase = params.get("phase") || "";
  const runId = params.get("run_id") || "";
  if (!isValidDate(date)) return { date, phase: "", runId: "", error: "目标港股日期无效，须为 YYYYMMDD" };
  if (phase && !PHASES.includes(phase as Phase)) return { date, phase: "", runId: "", error: "计划阶段无效" };
  if (runId.length > 180 || (runId && !/^[A-Za-z0-9_.:-]+$/.test(runId))) {
    return { date, phase: "", runId: "", error: "版本标识无效" };
  }
  return { date, phase: phase as Phase | "", runId, error: null };
}
export function routeSearch(route: WorkbenchRoute, previousSearch = ""): string {
  const params = new URLSearchParams(previousSearch);
  params.delete("plan_date");
  params.set("date", route.date);
  if (route.phase) params.set("phase", route.phase); else params.delete("phase");
  if (route.runId) params.set("run_id", route.runId); else params.delete("run_id");
  return "?" + params.toString();
}
