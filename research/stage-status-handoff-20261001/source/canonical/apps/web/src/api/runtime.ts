import type { TaskStatusResponse } from "../contracts/runtime";


export async function loadTaskStatus(
  date: string,
  signal?: AbortSignal,
): Promise<TaskStatusResponse> {
  const response = await fetch(
    `/api/v3/tasks/status?date=${encodeURIComponent(date)}`,
    { signal },
  );
  if (!response.ok) throw new Error("task status request failed");
  return response.json() as Promise<TaskStatusResponse>;
}
