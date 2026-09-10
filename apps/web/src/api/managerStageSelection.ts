import type { ManagerStageSelectionResponse } from "../contracts/managerStageSelection";
import { MANAGER_STAGE_ID } from "../contracts/managerStageSelection";
import { ManagerReadError } from "./selection";

/** Read one exact target date from the existing stage-center consumer route. */
export async function loadManagerStageSelectionExact(
  targetTradeDate: string,
  signal?: AbortSignal,
): Promise<ManagerStageSelectionResponse> {
  const query = new URLSearchParams({
    date: targetTradeDate,
    stage: MANAGER_STAGE_ID,
    limit: "50",
    market: "HK_CONNECT",
  });
  const requestInit: RequestInit = { cache: "no-store" };
  if (signal) requestInit.signal = signal;
  const response = await fetch(`/api/v3/manager/stage-selection?${query.toString()}`, requestInit);
  if (!response.ok) {
    throw new ManagerReadError(
      "HTTP_NON_2XX",
      response.status,
      `今日港股通阶段候选读取失败（HTTP ${response.status}）。`,
    );
  }
  return response.json() as Promise<ManagerStageSelectionResponse>;
}

export const loadStageSelectionExact = loadManagerStageSelectionExact;
