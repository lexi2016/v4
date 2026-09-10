import type { SelectionProduct } from "../contracts/selection";

export type ManagerReadErrorKind = "HTTP_NON_2XX";

export class ManagerReadError extends Error {
  readonly kind: ManagerReadErrorKind;
  readonly status: number;

  constructor(kind: ManagerReadErrorKind, status: number, message: string) {
    super(message);
    this.name = "ManagerReadError";
    this.kind = kind;
    this.status = status;
  }
}

/** Read exactly one target trade date; this module has no latest or write route. */
export async function loadSelectionExact(
  targetTradeDate: string,
  signal?: AbortSignal,
): Promise<SelectionProduct> {
  const requestInit: RequestInit = { cache: "no-store" };
  if (signal) requestInit.signal = signal;
  const response = await fetch(
    `/api/v3/research/selection?target_trade_date=${encodeURIComponent(targetTradeDate)}`,
    requestInit,
  );
  if (!response.ok) {
    throw new ManagerReadError(
      "HTTP_NON_2XX",
      response.status,
      `经理选股工作台读取失败（HTTP ${response.status}）。`,
    );
  }
  return response.json() as Promise<SelectionProduct>;
}

export const loadManagerSelectionExact = loadSelectionExact;
