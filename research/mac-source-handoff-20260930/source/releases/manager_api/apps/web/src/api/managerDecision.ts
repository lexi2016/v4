import type { ManagerDecisionResponse } from "../contracts/managerDecision";
import { ManagerReadError } from "./selection";

/** Read the independent manager decision DTO for one exact target date. */
export async function loadManagerDecisionExact(
  targetTradeDate: string,
  signal?: AbortSignal,
): Promise<ManagerDecisionResponse> {
  const requestInit: RequestInit = { cache: "no-store" };
  if (signal) requestInit.signal = signal;
  const response = await fetch(
    `/api/v3/research/selection/manager-decision?target_trade_date=${encodeURIComponent(targetTradeDate)}`,
    requestInit,
  );
  if (!response.ok) {
    throw new ManagerReadError(
      "HTTP_NON_2XX",
      response.status,
      `独立经理决策读取失败（HTTP ${response.status}）。`,
    );
  }
  return response.json() as Promise<ManagerDecisionResponse>;
}

export const loadManagerResearchDecisionExact = loadManagerDecisionExact;
