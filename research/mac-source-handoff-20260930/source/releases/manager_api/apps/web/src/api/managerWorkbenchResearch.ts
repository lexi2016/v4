import {
  MANAGER_WORKBENCH_MARKET,
  MANAGER_WORKBENCH_SLOT,
  validateManagerWorkbenchResearch,
  type ManagerWorkbenchResearchResponse,
} from "../contracts/managerWorkbenchResearch";

export class ManagerWorkbenchResearchRequestError extends Error {
  constructor(
    readonly code: "NETWORK_REJECTED" | "HTTP_NON_2XX" | "INVALID_RESPONSE",
    message: string,
    readonly status?: number,
    readonly cause?: unknown,
  ) {
    super(message);
    this.name = "ManagerWorkbenchResearchRequestError";
  }
}

export type ManagerWorkbenchResearchRequestOptions = Readonly<{ signal?: AbortSignal }>;

export async function loadManagerWorkbenchResearchExact(
  date: string,
  options: ManagerWorkbenchResearchRequestOptions = {},
): Promise<ManagerWorkbenchResearchResponse> {
  const params = new URLSearchParams({ date, market: MANAGER_WORKBENCH_MARKET, slot: MANAGER_WORKBENCH_SLOT });
  let response: Response;
  try {
    response = await fetch(`/api/v4/manager/workbench-research?${params.toString()}`, {
      cache: "no-store",
      signal: options.signal,
    });
  } catch (cause) {
    throw new ManagerWorkbenchResearchRequestError(
      "NETWORK_REJECTED",
      "经理工作台研究发现网络请求失败",
      undefined,
      cause,
    );
  }
  if (!response.ok) {
    throw new ManagerWorkbenchResearchRequestError(
      "HTTP_NON_2XX",
      `经理工作台研究发现读取失败（HTTP ${response.status}）`,
      response.status,
    );
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch (cause) {
    throw new ManagerWorkbenchResearchRequestError(
      "INVALID_RESPONSE",
      "经理工作台研究发现响应不是有效 JSON",
      undefined,
      cause,
    );
  }
  const issue = validateManagerWorkbenchResearch(payload, date);
  if (issue) {
    throw new ManagerWorkbenchResearchRequestError(
      "INVALID_RESPONSE",
      `经理工作台研究发现 contract 未通过：${issue}`,
    );
  }
  return payload as ManagerWorkbenchResearchResponse;
}
