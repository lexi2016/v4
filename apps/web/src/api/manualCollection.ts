export type CollectionTarget = "HK_STAGE" | "HK_CLOSE";
export type CollectionRequest = { date: string; target: CollectionTarget; stage_id?: string };
export type CollectionJob = {
  job_id: string; trade_date: string; target: CollectionTarget; stage_id: string | null;
  status: string; step: string; message: string; cannot_confirm: string[];
  result: {
    same_date_row_count?: number; universe_count?: number; coverage_ratio?: number;
    review_status?: string; missing_stages?: string[]; selection_status?: string;
    selected_rows?: number; source_rows?: number; backfill_run_id?: string; run_id?: string;
    snapshot_status?: string; requested_rows?: number; returned_rows?: number;
  };
};

export const collectionTerminal = (status: string) =>
  ["READY", "REUSED", "SNAPSHOT_CAPTURED", "PARTIAL", "CANNOT_CONFIRM"].includes(status);

async function readResponse(response: Response): Promise<CollectionJob> {
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail?.message || "补采请求未通过，请查看当前采集服务。");
  if (!/^[a-f0-9]{32}$/.test(payload.job_id) || typeof payload.trade_date !== "string") {
    throw new Error("补采回执身份无效。");
  }
  return payload as CollectionJob;
}

export async function startCollection(request: CollectionRequest, signal?: AbortSignal): Promise<CollectionJob> {
  return readResponse(await fetch("/api/v3/manual-collection", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request), signal,
  }));
}

export async function readCollection(jobId: string, signal?: AbortSignal): Promise<CollectionJob> {
  if (!/^[a-f0-9]{32}$/.test(jobId)) throw new Error("补采任务标识无效。");
  return readResponse(await fetch(`/api/v3/manual-collection/${jobId}`, { signal }));
}
