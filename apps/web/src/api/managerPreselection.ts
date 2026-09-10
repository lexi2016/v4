import type { ManagerPreselectionResponse } from "../contracts/managerPreselection";
import { ManagerReadError } from "./selection";

/** Read the exact requested D-1 preselection pool; no latest fallback or write route. */
export async function loadManagerPreselectionExact(
  targetDate: string,
  signal?: AbortSignal,
): Promise<ManagerPreselectionResponse> {
  const requestInit: RequestInit = { cache: "no-store" };
  if (signal) requestInit.signal = signal;
  const response = await fetch(
    `/api/v3/preselection-pools?date=${encodeURIComponent(targetDate)}&limit=200`,
    requestInit,
  );
  if (!response.ok) {
    throw new ManagerReadError(
      "HTTP_NON_2XX",
      response.status,
      `D-1 预选池读取失败（HTTP ${response.status}）。`,
    );
  }
  return response.json() as Promise<ManagerPreselectionResponse>;
}
